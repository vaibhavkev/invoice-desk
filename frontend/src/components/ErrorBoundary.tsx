import { Component, type ErrorInfo, type ReactNode } from 'react';
import { CircleX } from 'lucide-react';

interface Props {
  title: string;
  /** Clears the error when this changes, so navigating away recovers. */
  resetKey?: string;
  children: ReactNode;
}

/** Turns a render error below it into an inline box, so one bad payload never blanks the page. */
export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`${this.props.title}:`, error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="flex items-start gap-2 rounded-lg border border-reject-line bg-reject-soft px-3 py-2.5 text-sm text-reject-ink" role="alert">
        <CircleX className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <div className="min-w-0">
          <p className="font-semibold">{this.props.title}</p>
          <p className="mt-0.5 break-words font-mono text-xs">{error.message}</p>
        </div>
      </div>
    );
  }
}
