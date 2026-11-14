import { Component, type ReactNode } from "react";

/** Render and chunk-loading failures must give the engineer a recovery path, not a blank workspace. */
export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) return (
      <main className="mx-auto mt-16 max-w-xl p-6">
        <div role="alert" className="rounded-lg border border-red-200 bg-white p-6">
          <h1 className="text-lg font-semibold text-slate-900">The workspace could not be displayed</h1>
          <p className="mt-2 text-sm text-slate-600">Reload to recover your session and current URL. If this continues, contact a portal administrator.</p>
          <button type="button" className="btn-primary mt-4" onClick={() => window.location.reload()}>Reload portal</button>
        </div>
      </main>
    );
    return this.props.children;
  }
}
