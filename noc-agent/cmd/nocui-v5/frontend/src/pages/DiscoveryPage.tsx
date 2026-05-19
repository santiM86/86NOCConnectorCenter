import { useEffect, useState } from 'react'
import { Compass, ExternalLink, RefreshCcw, Radar, HardDrive, Cloud, AlertCircle } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { api, type DiscoveredEndpoint, type DiscoveryStatus } from '@/lib/bridge'
import { timeAgo } from '@/lib/utils'

export function DiscoveryPage() {
  const [items, setItems] = useState<DiscoveredEndpoint[]>([])
  const [status, setStatus] = useState<DiscoveryStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [rescanning, setRescanning] = useState(false)
  const [filter, setFilter] = useState('')

  const load = async () => {
    try {
      const [d, s] = await Promise.all([api.listDiscovered(), api.discoveryStatus()])
      setItems(d ?? [])
      setStatus(s ?? null)
    } catch {
      setItems([])
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5_000)
    return () => clearInterval(id)
  }, [])

  const triggerRescan = async () => {
    setRescanning(true)
    try {
      await api.forceRescan()
      // Il servizio scansiona entro 3s; aspettiamo 4s e ricarichiamo
      setTimeout(async () => {
        await load()
        setRescanning(false)
      }, 4500)
    } catch {
      setRescanning(false)
    }
  }

  const filtered = filter
    ? items.filter((d) => {
        const q = filter.toLowerCase()
        return (
          d.ip.toLowerCase().includes(q) ||
          (d.hostname ?? '').toLowerCase().includes(q) ||
          (d.mac ?? '').toLowerCase().includes(q) ||
          (d.vendor ?? '').toLowerCase().includes(q)
        )
      })
    : items

  return (
    <div className="p-6 space-y-5 h-full flex flex-col">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Passive Discovery</div>
          <h1 className="text-2xl font-bold tracking-tight">Dispositivi rilevati</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Endpoint scoperti dal connector via ARP, mDNS, PTR, NBNS. La cache locale rende la lista
            disponibile anche se il Center è offline.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button data-testid="discovery-open-dashboard" variant="outline" size="sm" onClick={() => api.openDashboard()}>
            <ExternalLink />
            Apri Dashboard
          </Button>
          <Button data-testid="discovery-refresh" variant="outline" size="sm" onClick={load}>
            <RefreshCcw />
            Aggiorna
          </Button>
          <Button
            data-testid="discovery-rescan"
            variant="default"
            size="sm"
            onClick={triggerRescan}
            disabled={rescanning}
          >
            <Radar className={rescanning ? 'animate-spin' : ''} />
            {rescanning ? 'Scansione in corso…' : 'Re-scan ora'}
          </Button>
        </div>
      </header>

      <StatusStrip status={status} count={items.length} loading={loading} />

      <div className="relative">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filtra per IP, hostname, MAC, vendor…"
          className="w-full sm:max-w-sm bg-secondary/30 border border-border rounded-md px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
          data-testid="discovery-filter"
        />
        {filter && (
          <span className="ml-2 text-xs text-muted-foreground">
            {filtered.length} di {items.length}
          </span>
        )}
      </div>

      <Card className="flex-1 overflow-hidden p-0">
        <ScrollArea className="h-full">
          {loading ? (
            <div className="p-10 text-center text-sm text-muted-foreground">Caricamento…</div>
          ) : filtered.length === 0 ? (
            <EmptyState noFilter={!filter} />
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-secondary/30 sticky top-0 z-10 backdrop-blur">
                <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left px-4 py-2.5 font-semibold">IP</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Hostname</th>
                  <th className="text-left px-4 py-2.5 font-semibold">MAC</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Vendor</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Last seen</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => (
                  <tr
                    key={`${d.ip}-${d.mac ?? ''}`}
                    className="border-t border-border/60 hover:bg-accent/5 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-xs">{d.ip}</td>
                    <td className="px-4 py-3">
                      {d.hostname || <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{d.mac || '—'}</td>
                    <td className="px-4 py-3 text-muted-foreground truncate max-w-[260px]">{d.vendor || '—'}</td>
                    <td className="px-4 py-3 text-muted-foreground">{timeAgo(d.last_seen_at)}</td>
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

function StatusStrip({
  status,
  count,
  loading,
}: {
  status: DiscoveryStatus | null
  count: number
  loading: boolean
}) {
  if (loading) return null
  const isLocal = status?.source === 'local'
  const isNone = !status || status.source === 'none'

  return (
    <div
      className="flex flex-wrap items-center gap-2 text-xs"
      data-testid="discovery-status-strip"
    >
      {isLocal && (
        <Badge variant="muted" className="gap-1.5">
          <HardDrive className="size-3" />
          Sorgente: cache locale
        </Badge>
      )}
      {!isLocal && !isNone && (
        <Badge variant="muted" className="gap-1.5">
          <Cloud className="size-3" />
          Sorgente: Center (fallback)
        </Badge>
      )}
      {isNone && (
        <Badge variant="muted" className="gap-1.5">
          <AlertCircle className="size-3" />
          Nessuna cache disponibile
        </Badge>
      )}
      <span className="text-muted-foreground">
        {count} endpoint
      </span>
      {status?.last_scan_at && (
        <span className="text-muted-foreground">
          · ultimo sweep {timeAgo(status.last_scan_at)}
        </span>
      )}
      {status?.written_at && (
        <span className="text-muted-foreground hidden sm:inline">
          · cache scritta {timeAgo(status.written_at)}
        </span>
      )}
    </div>
  )
}

function EmptyState({ noFilter }: { noFilter: boolean }) {
  return (
    <div className="p-16 text-center">
      <Compass className="size-10 mx-auto text-muted-foreground/40" />
      <div className="mt-3 text-sm font-medium">
        {noFilter ? 'Nessun endpoint scoperto' : 'Nessun risultato per il filtro'}
      </div>
      <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
        {noFilter
          ? 'Lo scanner passivo gira ogni 5 minuti. Clicca "Re-scan ora" per forzare uno sweep immediato.'
          : 'Prova a cambiare il filtro o premi "Re-scan ora" per arricchire la cache.'}
      </p>
    </div>
  )
}
