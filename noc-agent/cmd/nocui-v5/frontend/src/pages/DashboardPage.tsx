import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Activity, ArrowUpRight, Boxes, CheckCircle2, Clock, Compass, Cpu, Eye,
  Radio, RefreshCcw, Server, ShieldCheck, Signal, TriangleAlert, Wifi, Zap,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { api, type AgentInfo, type Device, type DiscoveredEndpoint, type HealthSnapshot } from '@/lib/bridge'
import { formatDuration, formatRtt, timeAgo } from '@/lib/utils'

interface Props {
  agent: AgentInfo | null
  health: HealthSnapshot | null
  onRefresh: () => void
  goto: (k: 'devices' | 'discovery' | 'logs') => void
}

export function DashboardPage({ agent, health, onRefresh, goto }: Props) {
  const [devices, setDevices] = useState<Device[]>([])
  const [discovered, setDiscovered] = useState<DiscoveredEndpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    let cancel = false
    const load = async () => {
      try {
        const [d, e] = await Promise.all([api.listDevices(), api.listDiscovered()])
        if (cancel) return
        setDevices(d ?? [])
        setDiscovered(e ?? [])
      } catch (_) {
        // silent — la UI mostra placeholder
      } finally {
        if (!cancel) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 30_000)
    return () => { cancel = true; clearInterval(id) }
  }, [])

  const online = devices.filter((d) => d.status === 'online').length
  const offline = devices.filter((d) => d.status === 'offline').length
  const pending = devices.filter((d) => d.status === 'pending').length

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.refreshAgent()
      const [d, e] = await Promise.all([api.listDevices(), api.listDiscovered()])
      setDevices(d ?? [])
      setDiscovered(e ?? [])
      onRefresh()
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Hero */}
      <section>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Argus Desktop</div>
            <h1 className="text-3xl font-bold tracking-tight mt-1">
              {health?.connected ? 'Tutto in linea.' : 'Connessione non attiva.'}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {agent?.hostname ? `Host: ${agent.hostname} • ` : ''}
              {agent?.client_id ? `Cliente: ${agent.client_id.slice(0, 8)}…` : 'Configurazione mancante'}
            </p>
          </div>
          <Button data-testid="refresh-dashboard" variant="outline" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCcw className={refreshing ? 'animate-spin' : ''} />
            Aggiorna
          </Button>
        </div>
      </section>

      {/* KPI Cards */}
      <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard
          title="DISPOSITIVI ONLINE"
          value={loading ? '—' : String(online)}
          delta={pending > 0 ? `${pending} in attesa di poll` : 'tutti monitorati'}
          icon={CheckCircle2}
          tone="success"
          onClick={() => goto('devices')}
        />
        <KpiCard
          title="DISPOSITIVI OFFLINE"
          value={loading ? '—' : String(offline)}
          delta={offline === 0 ? 'nessun allarme' : 'investigare'}
          icon={TriangleAlert}
          tone={offline === 0 ? 'success' : 'destructive'}
          onClick={() => goto('devices')}
        />
        <KpiCard
          title="SCOPERTI (24h)"
          value={loading ? '—' : String(discovered.length)}
          delta="ARP + mDNS"
          icon={Compass}
          tone="primary"
          onClick={() => goto('discovery')}
        />
        <KpiCard
          title="LATENZA CENTER"
          value={health?.rtt_ms ? `${health.rtt_ms.toFixed(1)} ms` : '—'}
          delta={health?.connected ? 'WSS ok' : 'disconnesso'}
          icon={Signal}
          tone={health?.connected ? 'primary' : 'destructive'}
        />
      </section>

      {/* Agent panel + activity feed */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Stato Agent</CardTitle>
              <Badge variant={agent?.service_state === 'running' ? 'success' : 'destructive'}>
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
              <Field icon={Wifi} label="Backend" value={agent?.backend_url ? new URL(agent.backend_url).host : '—'} />
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
              <Button data-testid="btn-view-logs" variant="ghost" size="sm" onClick={() => goto('logs')} className="ml-auto">
                Vai ai log
                <ArrowUpRight />
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Attività Recente</CardTitle>
          </CardHeader>
          <CardContent>
            <ActivityFeed devices={devices} discovered={discovered} health={health} />
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

function ActivityFeed({
  devices, discovered, health,
}: { devices: Device[]; discovered: DiscoveredEndpoint[]; health: HealthSnapshot | null }) {
  const events = [
    ...(health?.connected ? [{ icon: Radio, color: 'text-success', title: 'WebSocket connesso', desc: `RTT ${health.rtt_ms?.toFixed(1)}ms`, when: health.connected_at }] : []),
    ...discovered.slice(0, 5).map((d) => ({ icon: Compass, color: 'text-primary', title: `Nuovo endpoint ${d.ip}`, desc: d.vendor || d.hostname || d.mac || d.source, when: d.last_seen_at })),
    ...devices.filter((d) => d.status === 'offline').slice(0, 3).map((d) => ({ icon: TriangleAlert, color: 'text-destructive', title: `${d.name || d.ip} offline`, desc: 'ICMP non raggiungibile', when: d.last_poll_at })),
  ].slice(0, 8)

  if (events.length === 0) {
    return (
      <div className="text-xs text-muted-foreground py-8 text-center">
        Nessuna attività ancora.
      </div>
    )
  }

  return (
    <ul className="space-y-3">
      {events.map((e, i) => {
        const Icon = e.icon
        return (
          <li key={i} className="flex items-start gap-3 animate-slide-in" style={{ animationDelay: `${i * 30}ms` }}>
            <div className={`mt-0.5 ${e.color}`}>
              <Icon className="size-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{e.title}</div>
              {e.desc && <div className="text-xs text-muted-foreground truncate">{e.desc}</div>}
            </div>
            <div className="text-[10px] text-muted-foreground shrink-0">{timeAgo(e.when as string | undefined)}</div>
          </li>
        )
      })}
    </ul>
  )
}
