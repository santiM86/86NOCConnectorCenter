import { useEffect, useState } from 'react'
import { AppShell } from './components/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { SettingsPage } from './pages/SettingsPage'
import { api, type AgentInfo, type HealthSnapshot } from './lib/bridge'

// Connector "headless-style" UI: tutta la gestione operativa (Dispositivi,
// Auto-Discovery, Scanner LAN, Diagnostica/Log) vive ora nel NOC Center web.
// Localmente esponiamo solo Dashboard (stato connessione + identità) e
// Impostazioni (controllo servizio come lifeline se il Center è giù).
type NavKey = 'dashboard' | 'settings'

export function App() {
  const [active, setActive] = useState<NavKey>('dashboard')
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [health, setHealth] = useState<HealthSnapshot | null>(null)

  // Initial load + periodic refresh.
  useEffect(() => {
    let stopped = false
    const tick = async () => {
      try {
        const [a, h] = await Promise.all([api.agentSnapshot(), api.healthCheck()])
        if (!stopped) {
          setAgent(a)
          setHealth(h)
        }
      } catch {
        /* ignore */
      }
    }
    tick()
    const id = setInterval(tick, 10_000)
    return () => { stopped = true; clearInterval(id) }
  }, [])

  // Subscribe to backend events (agent service state changes).
  useEffect(() => {
    if (typeof window === 'undefined' || !window.runtime) return
    const handler = (...args: unknown[]) => {
      const info = args[0] as AgentInfo | undefined
      if (info) setAgent(info)
    }
    window.runtime.EventsOn('agent:updated', handler)
    return () => window.runtime?.EventsOff('agent:updated')
  }, [])

  return (
    <AppShell active={active} onNavigate={(k) => setActive(k as NavKey)} agent={agent} health={health}>
      {active === 'dashboard' && (
        <DashboardPage
          agent={agent}
          health={health}
          onRefresh={() => api.healthCheck().then(setHealth)}
        />
      )}
      {active === 'settings' && <SettingsPage agent={agent} />}
    </AppShell>
  )
}
