import React from "react";
import { Warning } from "@phosphor-icons/react";

/**
 * Lightweight Error Boundary: previene il "tutto nero" quando un sotto-componente
 * crasha (es. "Objects are not valid as React child", undefined.method, ecc.).
 * Mostra un fallback inline con il messaggio di errore + bottone retry.
 *
 * Uso:
 *   <ErrorBoundary label="Scheda dispositivo">
 *     <DeviceInfoCard ... />
 *   </ErrorBoundary>
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    // log to console for dev debugging; in prod si potrebbe inviare a Sentry/etc
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", this.props.label || "(unlabeled)", error, errorInfo);
    this.setState({ errorInfo });
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      const msg = String(this.state.error?.message || this.state.error || "Errore sconosciuto");
      return (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 m-2" data-testid="error-boundary-fallback">
          <div className="flex items-start gap-3">
            <Warning size={20} weight="fill" className="text-red-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <h4 className="text-sm font-semibold text-red-200">
                Errore caricamento {this.props.label || "componente"}
              </h4>
              <p className="text-xs text-red-100/80 mt-1 break-words">
                {msg}
              </p>
              {this.props.hint && (
                <p className="text-xs text-red-100/60 mt-1 italic">{this.props.hint}</p>
              )}
              <button
                onClick={this.handleRetry}
                className="mt-2 px-3 py-1 text-xs rounded-md border border-red-500/40 text-red-200 hover:bg-red-500/20"
                data-testid="error-boundary-retry"
              >
                Riprova
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
