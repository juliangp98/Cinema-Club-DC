import { Component } from "react";

// A crash anywhere shows this instead of a blank page (R7b). "Reload" starts
// clean: the installed app's stored files are dropped, so an out-of-date copy
// can't keep failing (that used to take clearing the browser's history).
export async function cleanReload() {
  try {
    const regs = (await navigator.serviceWorker?.getRegistrations?.()) || [];
    await Promise.all(regs.map(r => r.unregister()));
    const keys = (await window.caches?.keys?.()) || [];
    await Promise.all(keys.map(k => window.caches.delete(k)));
  } catch { /* reload anyway */ }
  window.location.reload();
}

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error, info) {
    console.error("App crashed:", error, info?.componentStack);
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="crash-screen" role="alert">
        <span className="deco crash-title">Cinema Club DC</span>
        <p>“Houston, we have a problem.” Something went wrong showing this page.</p>
        <button type="button" className="btn btn-primary" onClick={cleanReload}>Reload</button>
      </div>
    );
  }
}
