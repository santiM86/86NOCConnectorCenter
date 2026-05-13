/// <reference types="vite/client" />

// Wails iniettato globalmente. Tipizzato in modo permissivo perché i
// bindings vengono generati da `wails dev`/`wails build` in
// `frontend/wailsjs/go/main/App.d.ts`. In dev, il frontend gira anche
// senza Wails (mock disabilitato → API resi promise vuoti).
declare global {
  interface Window {
    runtime?: {
      EventsOn: (eventName: string, callback: (...args: unknown[]) => void) => void
      EventsOff: (eventName: string) => void
      WindowMinimise: () => void
      WindowToggleMaximise: () => void
      WindowHide: () => void
      Quit: () => void
    }
    go?: {
      main?: {
        App?: Record<string, (...args: unknown[]) => Promise<unknown>>
      }
    }
  }
}

export {}
