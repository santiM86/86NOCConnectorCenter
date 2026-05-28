/**
 * SafeBoundary — minimal error boundary che renderizza children e, in caso
 * di crash, mostra un piccolo banner di errore inline al posto di portare
 * giu' l'intera pagina (schermo nero).
 *
 * Usato per wrappare componenti "rischiosi" che dipendono da nuovi endpoint
 * backend (es. BridgeHealthWidget) → se il backend non e' aggiornato, il
 * componente NON deve far crashare il resto della pagina.
 */
import React from "react";

export default class SafeBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.warn("[SafeBoundary] caught error:", error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      const label = this.props.label || "Sezione opzionale";
      return (
        <div
          className="text-[10px] px-2 py-1.5 rounded border border-yellow-500/30 bg-yellow-500/5 text-yellow-300"
          data-testid="safe-boundary-fallback"
          title={String(this.state.error)}
        >
          ⚠ {label} non disponibile (errore client). Il resto della pagina e' funzionante.
        </div>
      );
    }
    return this.props.children;
  }
}
