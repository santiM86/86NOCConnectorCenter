import { useEffect, useMemo, useState } from 'react'
import { Boxes, RefreshCcw, Search, Zap } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { api, type Device } from '@/lib/bridge'
import { formatRtt, timeAgo, cn } from '@/lib/utils'

export function DevicesPage() {
  const [items, setItems] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'online' | 'offline' | 'pending'>('all')
  const [pingingIp, setPingingIp] = useState<string | null>(null)

  const load = async () => {
    try {
      const d = await api.listDevices()
      setItems(d ?? [])
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
    const id = setInterval(load, 15_000)
    return () => clearInterval(id)
  }, [])

  const filtered = useMemo(() => {
    return items.filter((d) => {
      if (filter !== 'all' && d.status !== filter) return false
      if (!query) return true
      const q = query.toLowerCase()
      return (
        d.ip.toLowerCase().includes(q) ||
        (d.name || '').toLowerCase().includes(q) ||
        (d.device_type || '').toLowerCase().includes(q)
      )
    })
  }, [items, query, filter])

  const counts = useMemo(() => ({
    all: items.length,
    online: items.filter((d) => d.status === 'online').length,
    offline: items.filter((d) => d.status === 'offline').length,
    pending: items.filter((d) => d.status === 'pending').length,
  }), [items])

  const handlePing = async (ip: string) => {
    setPingingIp(ip)
    try { await api.testPing(ip) } catch {}
    finally {
      setPingingIp(null)
      load()
    }
  }

  return (
    <div className="p-6 space-y-5 h-full flex flex-col">
      <header className="flex items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Live Monitoring</div>
          <h1 className="text-2xl font-bold tracking-tight">Dispositivi</h1>
        </div>
        <Button data-testid="devices-refresh" variant="outline" size="sm" onClick={load}>
          <RefreshCcw />
          Aggiorna
        </Button>
      </header>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative max-w-sm flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            data-testid="devices-search"
            placeholder="Cerca per IP, nome, tipo…"
            className="pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <FilterChip label="Tutti" count={counts.all} active={filter === 'all'} onClick={() => setFilter('all')} />
        <FilterChip label="Online" count={counts.online} active={filter === 'online'} onClick={() => setFilter('online')} tone="success" />
        <FilterChip label="Offline" count={counts.offline} active={filter === 'offline'} onClick={() => setFilter('offline')} tone="destructive" />
        <FilterChip label="Pending" count={counts.pending} active={filter === 'pending'} onClick={() => setFilter('pending')} tone="warning" />
      </div>

      <Card className="flex-1 overflow-hidden p-0">
        <ScrollArea className="h-full">
          {loading ? (
            <SkeletonRows />
          ) : filtered.length === 0 ? (
            <div className="p-10 text-center text-sm text-muted-foreground">
              Nessun dispositivo trovato.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-secondary/30 sticky top-0 backdrop-blur z-10">
                <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left px-4 py-2.5 font-semibold w-32">Stato</th>
                  <th className="text-left px-4 py-2.5 font-semibold">IP / Nome</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Tipo</th>
                  <th className="text-left px-4 py-2.5 font-semibold">RTT</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Ultimo poll</th>
                  <th className="text-right px-4 py-2.5 font-semibold">Azioni</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => (
                  <tr key={d.ip} className="border-t border-border/60 hover:bg-accent/5 transition-colors" data-testid={`device-row-${d.ip}`}>
                    <td className="px-4 py-3">
                      <StatusBadge state={d.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium truncate">{d.name || d.ip}</div>
                      {d.name && <div className="text-xs text-muted-foreground font-mono">{d.ip}</div>}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{d.device_type || '—'}</td>
                    <td className="px-4 py-3 font-mono text-xs">{d.latency_ms ? `${d.latency_ms.toFixed(1)}ms` : '—'}</td>
                    <td className="px-4 py-3 text-muted-foreground">{timeAgo(d.last_poll_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <Button
                        data-testid={`device-ping-${d.ip}`}
                        variant="ghost"
                        size="sm"
                        onClick={() => handlePing(d.ip)}
                        disabled={pingingIp === d.ip}
                      >
                        <Zap className={pingingIp === d.ip ? 'animate-pulse' : ''} />
                        Ping
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </ScrollArea>
      </Card>
    </div>
  )
}

function StatusBadge({ state }: { state: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    online:  { label: 'ONLINE',  cls: 'bg-success/15 text-success' },
    offline: { label: 'OFFLINE', cls: 'bg-destructive/15 text-destructive' },
    pending: { label: 'PENDING', cls: 'bg-warning/15 text-warning' },
  }
  const m = map[state] ?? { label: state.toUpperCase(), cls: 'bg-muted text-muted-foreground' }
  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold tracking-wider', m.cls)}>
      <span className="size-1.5 rounded-full bg-current animate-pulse-dot" />
      {m.label}
    </span>
  )
}

function FilterChip({ label, count, active, onClick, tone }: {
  label: string; count: number; active: boolean; onClick: () => void; tone?: 'success' | 'destructive' | 'warning'
}) {
  const accent =
    tone === 'success' ? 'data-[on=true]:border-success/40 data-[on=true]:text-success' :
    tone === 'destructive' ? 'data-[on=true]:border-destructive/40 data-[on=true]:text-destructive' :
    tone === 'warning' ? 'data-[on=true]:border-warning/40 data-[on=true]:text-warning' :
    'data-[on=true]:border-primary/40 data-[on=true]:text-primary'
  return (
    <button
      data-testid={`filter-${label.toLowerCase()}`}
      data-on={active}
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 px-3 py-1.5 rounded-md border border-border bg-card text-xs font-medium text-muted-foreground hover:text-foreground transition-colors',
        accent
      )}
    >
      {label}
      <span className="text-[10px] opacity-70">{count}</span>
    </button>
  )
}

function SkeletonRows() {
  return (
    <div className="p-4 space-y-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-12 rounded shimmer-bg" />
      ))}
    </div>
  )
}
