/**
 * Top-level error boundary. A render-time throw anywhere in the tree (e.g. a
 * malformed imported project bundle reaching a chart) otherwise unmounts the
 * whole app to a blank screen — "it crashes and stops". This catches it and
 * shows a recoverable message with the error, so the user can reload instead of
 * losing the window.
 */
import React from 'react';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Surface to the console so the stack is inspectable in DevTools.
    // eslint-disable-next-line no-console
    console.error('Ragnarok crashed while rendering:', error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render(): React.ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="app-crash" role="alert">
        <div className="app-crash-card">
          <h2>Something went wrong.</h2>
          <p>
            Ragnarok hit an unexpected error while rendering — usually a malformed
            import. Your work in the backend session is safe. Try again, and if it
            keeps happening, reload.
          </p>
          <pre className="app-crash-detail">{error.message}</pre>
          <div className="app-crash-actions">
            <button className="run-button" onClick={() => window.location.reload()}>Reload</button>
            <button className="tb-btn" onClick={this.reset}>Try to continue</button>
          </div>
        </div>
      </div>
    );
  }
}
