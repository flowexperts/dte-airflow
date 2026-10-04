import { Component, type ReactNode } from "react";
import { humanizeError } from "@/lib/errors";

/** Catches render errors so a DTE bug shows a message, not a blank Airflow page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("DTE error boundary caught:", error);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const human = humanizeError(error);
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
        <h2 className="text-2xl font-semibold">{human.title}</h2>
        <p className="max-w-md text-sm text-muted">{human.message}</p>
        {human.detail && (
          <details className="max-w-md text-left">
            <summary className="cursor-pointer font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-text">
              Show technical details
            </summary>
            <pre className="mt-2 font-mono text-[11.5px] text-subtle whitespace-pre-wrap break-words max-h-56 overflow-auto">
              {human.detail}
            </pre>
          </details>
        )}
        <button
          onClick={() => this.setState({ error: null })}
          className="rounded-md border border-border bg-surface px-4 py-2 text-sm hover:bg-surface/70"
        >
          Try again
        </button>
      </div>
    );
  }
}
