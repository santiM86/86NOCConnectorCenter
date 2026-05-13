import { useEffect, useState } from 'react'
import { Compass, ExternalLink, RefreshCcw } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { api, type DiscoveredEndpoint } from '@/lib/bridge'
import { timeAgo } from '@/lib/utils'

export function DiscoveryPage() {
  const [items, setItems] = useState<DiscoveredEndpoint[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const d = await api.listDiscovered()
      setItems(d ?? [])
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
    const id = setInterval(load, 20_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="p-6 space-y-5 h-full flex flex-col">
      <header className="flex items-end justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Passive Discovery</div>
          <h1 className="text-2xl font-bold tracking-tight">Auto-Discovery</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Endpoint rilevati via ARP, mDNS e PTR sulle LAN del cliente. Approva o ignora dalla dashboard web.
          </p>
        </div>
        <div className="flex gap-2">
          <Button data-testid="discovery-open-dashboard" variant="outline" size="sm" onClick={() => api.openDashboard()}>
            <ExternalLink />
            Apri Dashboard
          </Button>
          <Button data-testid="discovery-refresh" variant="outline" size="sm" onClick={load}>
            <RefreshCcw />
            Aggiorna
          </Button>
        </div>
      </header>

      <Card className="flex-1 overflow-hidden p-0">
        <ScrollArea className="h-full">
          {loading ? (
            <div className="p-10 text-center text-sm text-muted-foreground">Caricamento…</div>
          ) : items.length === 0 ? (
            <EmptyState />
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-secondary/30 sticky top-0 z-10 backdrop-blur">
                <tr className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left px-4 py-2.5 font-semibold">IP</th>
                  <th className="text-left px-4 py-2.5 font-semibold">MAC</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Hostname</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Vendor</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Sorgente</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Visto</th>
                </tr>
              </thead>
              <tbody>
                {items.map((d) => (
                  <tr key={`${d.ip}-${d.mac}`} className="border-t border-border/60 hover:bg-accent/5 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs">{d.ip}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{d.mac || '—'}</td>
                    <td className="px-4 py-3">{d.hostname || <span className="text-muted-foreground">—</span>}</td>
                    <td className="px-4 py-3 text-muted-foreground">{d.vendor || '—'}</td>
                    <td className="px-4 py-3"><Badge variant="muted">{d.source}</Badge></td>
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

function EmptyState() {
  return (
    <div className="p-16 text-center">
      <Compass className="size-10 mx-auto text-muted-foreground/40" />
      <div className="mt-3 text-sm font-medium">Nessun endpoint scoperto</div>
      <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
        Lo scanner gira ogni 5 minuti. Se sei appena partito attendi qualche minuto.
      </p>
    </div>
  )
}
