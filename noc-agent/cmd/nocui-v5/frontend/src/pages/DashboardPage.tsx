import { motion } from 'framer-motion'
import {
  Activity, Clock, Cpu, Eye, ExternalLink, RefreshCcw, Server,
  ShieldCheck, Signal, Wifi,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { api, type AgentInfo, type HealthSnapshot } from '@/lib/bridge'
import { timeAgo } from '@/lib/utils'

interface Props {
  agent: AgentInfo | null
  health: HealthSnapshot | null
  onRefresh: () => void
}

export function DashboardPage({ agent, health, onRefresh }: Props) {
  const connected = !!health?.connected
  const serviceRunning = agent?.service_state === 'running'

  const handleRefresh = async () => {
    await api.refreshAgent()
    onRefresh()
  }

  return (
    <div className="p-6 space-y-6">
      {/* Hero */}
      <section>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Argus Desktop</div>
            <h1 className="text-3xl font-bold tracking-tight mt-1">
              {connected ? 'Tutto in linea.' : 'Connessione non attiva.'}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {agent?.hostname ? `Host: ${agent.hostname} • ` : ''}
              {agent?.client_id ? `Cliente: ${agent.client_id.slice(0, 8)}…` : 'Configurazione mancante'}
            </p>
          </div>
          <Button data-testid="refresh-dashboard" variant="outline" onClick={handleRefresh}>
            <RefreshCcw />
            Aggiorna
          </Button>
        </div>
      </section>

      {/* Hint headless */}
      <div className="rounded-lg border border-border/60 bg-card/40 px-4 py-3 text-xs text-muted-foreground">
        Gestione dispositivi, scansioni e log sono ora disponibili nel
        <span className="font-medium text-foreground"> NOC Center</span>.
        Questo Connector resta come servizio in background.
      </div>

      {/* KPI Cards - solo stato connessione */}
      <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard
          title="CENTER"
          value={connected ? 'ONLINE' : 'OFFLINE'}
          delta={connected ? 'WSS attivo' : (health?.error || 'disconnesso')}
          icon={Wifi}
          tone={connected ? 'success' : 'destructive'}
        />
        <KpiCard
          title="SERVIZIO AGENT"
          value={(agent?.service_state ?? 'unknown').toUpperCase()}
          delta={serviceRunning ? 'in esecuzione' : 'non attivo'}
          icon={Cpu}
          tone={serviceRunning ? 'success' : 'warning'}
        />
        <KpiCard
          title="LATENZA CENTER"
          value={health?.rtt_ms ? `${health.rtt_ms.toFixed(1)} ms` : '—'}
          delta={connected ? 'WSS ok' : 'disconnesso'}
          icon={Signal}
          tone={connected ? 'primary' : 'destructive'}
        />
        <KpiCard
          title="AGENT VERSIONE"
          value={agent?.agent_version || '—'}
          delta={health?.agents_online != null ? `${health.agents_online} agent collegati` : ''}
          icon={ShieldCheck}
          tone="primary"
        />
      </section>

      {/* Agent panel */}
      <section className="grid grid-cols-1 gap-4">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Stato Agent</CardTitle>
              <Badge variant={serviceRunning ? 'success' : 'destructive'}>
                {agent?.service_state ?? 'unknown'}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
              <Field icon={Server} label="Hostname" value={agent?.hostname || '—'} />
              <Field icon={Cpu} label="Versione" value={agent?.agent_version || '—'} />
              <Field icon={ShieldCheck} label="Ruolo" value={agent?.role || '—'} />
              <Field icon={Activity} label="Watchdog" value={agent?.watchdog_state || '—'} />
              <Field icon={Wifi} label="Backend" value={agent?.backend_url ? safeHost(agent.backend_url) : '—'} />
              <Field icon={Clock} label="Sessione da" value={health?.connected_at ? timeAgo(health.connected_at) : '—'} />
            </div>
            <div className="flex items-center gap-2 pt-2 border-t border-border/60">
              <Button data-testid="btn-restart" variant="outline" size="sm" onClick={() => api.restartService()}>
                <RefreshCcw />
                Riavvia servizio
              </Button>
              <Button data-testid="btn-open-config" variant="ghost" size="sm" onClick={() => api.openConfig()}>
                <Eye />
                agent.yaml
              </Button>
              <Button data-testid="btn-open-center" variant="ghost" size="sm" onClick={() => api.openDashboard()} className="ml-auto">
                Apri NOC Center
                <ExternalLink />
              </Button>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

interface KpiProps {
  title: string
  value: string
  delta?: string
  icon: React.ComponentType<{ className?: string }>
  tone: 'success' | 'destructive' | 'primary' | 'warning'
  onClick?: () => void
}
function KpiCard({ title, value, delta, icon: Icon, tone, onClick }: KpiProps) {
  const toneClass =
    tone === 'success' ? 'text-success' :
    tone === 'destructive' ? 'text-destructive' :
    tone === 'warning' ? 'text-warning' :
    'text-primary'
  return (
    <motion.div whileHover={{ y: -2 }} transition={{ duration: 0.15 }}>
      <Card
        onClick={onClick}
        className={onClick ? 'cursor-pointer hover:border-primary/40 transition-colors' : ''}
      >
        <CardContent className="p-5">
          <div className="flex items-start justify-between">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{title}</div>
            <Icon className={`size-4 ${toneClass}`} />
          </div>
          <div className="mt-3 text-3xl font-bold tracking-tight">{value}</div>
          {delta && <div className="text-xs text-muted-foreground mt-1">{delta}</div>}
        </CardContent>
      </Card>
    </motion.div>
  )
}

function Field({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <Icon className="size-4 mt-0.5 text-muted-foreground" />
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-sm font-medium truncate" title={value}>{value}</div>
      </div>
    </div>
  )
}

function safeHost(u: string): string {
  try {
    return new URL(u).host
  } catch {
    return u
  }
}
