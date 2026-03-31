import React from "react";
import { Panel } from "./Panel";
import { ScrollArea } from "./ScrollArea";

type Props = {
  children: React.ReactNode;
};

type State = {
  error: Error | null;
  info: React.ErrorInfo | null;
};

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = {
    error: null,
    info: null,
  };

  static getDerivedStateFromError(error: Error): State {
    return { error, info: null };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({ error, info });
    console.error("Sol UI ErrorBoundary caught:", error, info);
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    return (
      <div className="h-full w-full bg-slate-50">
        <div className="min-h-screen min-w-0 p-4">
          <Panel className="p-4">
            <div className="text-lg font-semibold text-rose-600">Sol UI Error</div>
            <ScrollArea className="max-h-[60vh]">
              <div className="mt-3 space-y-2 text-sm">
                <div className="font-medium">Message:</div>
                <pre className="rounded-md border border-rose-200 bg-rose-50/80 p-3 text-xs text-rose-800">
                  {this.state.error.message}
                </pre>
                {this.state.info?.componentStack && (
                  <>
                    <div className="font-medium">Stack:</div>
                    <pre className="rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-700">
                      {this.state.info.componentStack}
                    </pre>
                  </>
                )}
              </div>
            </ScrollArea>
          </Panel>
        </div>
      </div>
    );
  }
}
