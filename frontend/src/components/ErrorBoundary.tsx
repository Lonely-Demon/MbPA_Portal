import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

/**
 * L-2: without this, an unhandled render error on any page produced a blank
 * white screen with no recovery UI. React only supports error boundaries as
 * class components — there is no hook equivalent.
 */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled error in application:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-paper flex items-center justify-center p-6">
          <div className="w-full max-w-md bg-white rounded-lg shadow-lg p-8 text-center">
            <h1 className="text-lg font-bold text-harbour mb-2">Something went wrong</h1>
            <p className="text-slate text-sm mb-6">
              An unexpected error occurred. Try reloading the page.
            </p>
            <button
              type="button"
              onClick={() => window.location.assign("/")}
              className="rounded bg-harbour text-white font-medium py-2 px-5 text-sm hover:bg-harbour-light transition-colors"
            >
              Return to sign in
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
