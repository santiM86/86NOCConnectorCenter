import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Play,
  Square,
  Wifi,
  RefreshCcw,
  Globe,
  Folder,
  Search,
  Loader2,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'

import { api, on, type ScanResult, type ScanProgress, type ScanDone } from '@/lib/bridge'

type Row = ScanResult

/**
 * Scanner LAN — UI nativa Wails.
 *
 * Lo Scanner gira *nel processo Go* (binding `StartLanScan`) e i risultati
 * arrivano qui via eventi (`scan:result`, `scan:progress`, `scan:done`).
 * Niente blocchi della finestra, niente "Non risponde": il WebView2 è
 * completamente disaccoppiato dal worker goroutine.
 */
export function ScannerPage() {
  const [cidr, setCidr] = useState('')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<ScanProgress>({ done: 0, total: 0, found: 0 })
  const [rows, setRows] = useState<Row[]>([])
  const [filter, setFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [duration, setDuration] = useState<number | null>(null)

  const startedAt = useRef<number | null>(null)
  const rowsRef = useRef<Map<string, Row>>(new Map())

  // Hydrate default CIDR (es. "192.168.1.0/24")
  useEffect(() => {
    api.defaultScanCIDR().then((c) => {
      if (c && !cidr) setCidr(c)
    }).catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Subscribe agli eventi Wails per streaming risultati.
  useEffect(() => {
    const offResult = on('scan:result', (raw) => {
      const r = raw as ScanResult
      const map = rowsRef.current
      const prev = map.get(r.ip)
      // Merge intelligente: tieni i campi non-vuoti più recenti.
      const merged: Row = {
        ip: r.ip,
        mac: r.mac || prev?.mac,
        hostname: r.hostname || prev?.hostname,
        vendor: r.vendor || prev?.vendor,
        status: r.status === 'arp-only' && prev?.status === 'alive' ? prev.status : r.status,
        rtt_ms: r.rtt_ms >= 0 ? r.rtt_ms : (prev?.rtt_ms ?? -1),
      }
      map.set(r.ip, merged)
      setRows(Array.from(map.values()).sort((a, b) => ipNum(a.ip) - ipNum(b.ip)))
    })
    const offProgress = on('scan:progress', (raw) => {
      setProgress(raw as ScanProgress)
    })
    const offDone = on('scan:done', (raw) => {
      const d = raw as ScanDone
      setRunning(false)
      if (d.error) setError(d.error)
      if (startedAt.current) {
        setDuration((Date.now() - startedAt.current) / 1000)
      }
    })
    return () => {
      offResult()
      offProgress()
      offDone()
    }
  }, [])

  const start = async () => {
    if (!cidr.trim()) return
    rowsRef.current.clear()
    setRows([])
    setError(null)
    setProgress({ done: 0, total: 0, found: 0 })
    setDuration(null)
    setRunning(true)
    startedAt.current = Date.now()
    try {
      await api.startLanScan(cidr.trim())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
      setRunning(false)
    }
  }

  const cancel = async () => {
    try {
      await api.cancelLanScan()
    } catch {
      /* ignore */
    }
    setRunning(false)
  }

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) =>
      [r.ip, r.hostname, r.mac, r.vendor].some((v) => v?.toLowerCase().includes(q)),
    )
  }, [rows, filter])

  const aliveCount = rows.filter((r) => r.status === 'alive').length
  const arpCount = rows.filter((r) => r.status === 'arp-only').length
  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0

  return (
    <div className="p-6 space-y-5" data-testid="scanner-page">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
            Network discovery
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Scanner LAN</h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Sweep ARP + ICMP nativo + NBNS + reverse DNS sulla subnet. Streaming live nel
            WebView2 — niente freeze della finestra.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          {!running ? (
            <Badge variant="outline" className="font-mono">
              {rows.length} device
            </Badge>
          ) : (
            <Badge className="bg-primary/15 text-primary font-mono animate-pulse">
              SCAN IN CORSO
            </Badge>
          )}
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wifi className="size-4" /> Range scansione
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_auto] gap-3 items-end">
            <div>
              <label className="text-xs text-muted-foreground">CIDR target</label>
              <Input
                data-testid="scanner-subnet"
                value={cidr}
                onChange={(e) => setCidr(e.target.value)}
                placeholder="es. 192.168.1.0/24"
                className="mt-1 font-mono"
                disabled={running}
              />
            </div>
            {!running ? (
              <Button data-testid="scanner-start" onClick={start} className="min-w-36">
                <Play className="size-4" /> Avvia scansione
              </Button>
            ) : (
              <Button
                data-testid="scanner-cancel"
                onClick={cancel}
                variant="destructive"
                className="min-w-36"
              >
                <Square className="size-4" /> Annulla
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => api.defaultScanCIDR().then(setCidr)}
              disabled={running}
              title="Rileva subnet locale"
            >
              <RefreshCcw className="size-4" />
            </Button>
          </div>

          {(running || progress.total > 0) && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2">
              <Progress value={pct} className="h-2" />
              <div className="text-xs text-muted-foreground flex items-center gap-3 flex-wrap font-mono">
                {running ? (
                  <Loader2 className="size-3 animate-spin text-primary" />
                ) : (
                  <CheckCircle2 className="size-3 text-emerald-500" />
                )}
                <span>
                  {progress.done}/{progress.total} probe
                </span>
                <span className="text-emerald-500">● {aliveCount} alive</span>
                {arpCount > 0 && <span className="text-amber-500">◐ {arpCount} arp-only</span>}
                {duration !== null && (
                  <span className="text-muted-foreground">in {duration.toFixed(1)}s</span>
                )}
              </div>
            </motion.div>
          )}

          {error && (
            <div className="text-sm rounded-md border border-destructive/30 bg-destructive/10 text-destructive px-3 py-2.5 flex items-start gap-2">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle>Risultati</CardTitle>
          <div className="relative w-64">
            <Search className="size-3.5 absolute left-2.5 top-2.5 text-muted-foreground" />
            <Input
              data-testid="scanner-filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="filtro: ip, hostname, mac…"
              className="pl-8 h-8 text-xs"
            />
          </div>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[440px] rounded-md border">
            <table className="w-full text-sm" data-testid="scanner-results">
              <thead className="bg-muted/50 sticky top-0 z-10 text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-3 py-2 w-24">Stato</th>
                  <th className="text-left px-3 py-2 font-mono w-32">IP</th>
                  <th className="text-left px-3 py-2 w-20">RTT</th>
                  <th className="text-left px-3 py-2">Hostname</th>
                  <th className="text-left px-3 py-2 font-mono">MAC</th>
                  <th className="text-left px-3 py-2">Vendor</th>
                  <th className="text-right px-3 py-2 w-32">Azioni</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center text-muted-foreground py-12">
                      {running
                        ? 'Scansione in corso…'
                        : 'Nessun risultato. Avvia una scansione per iniziare.'}
                    </td>
                  </tr>
                ) : (
                  filtered.map((r) => (
                    <tr
                      key={r.ip}
                      className="border-t hover:bg-muted/40 transition-colors"
                      data-testid={`scanner-row-${r.ip}`}
                    >
                      <td className="px-3 py-1.5">
                        {r.status === 'alive' ? (
                          <span className="text-emerald-500 font-medium">● alive</span>
                        ) : r.status === 'arp-only' ? (
                          <span className="text-amber-500 font-medium">◐ arp</span>
                        ) : (
                          <span className="text-muted-foreground">○ {r.status}</span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 font-mono">{r.ip}</td>
                      <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
                        {r.rtt_ms >= 0 ? `${r.rtt_ms} ms` : ''}
                      </td>
                      <td className="px-3 py-1.5">{r.hostname || ''}</td>
                      <td className="px-3 py-1.5 font-mono text-xs">{r.mac || ''}</td>
                      <td className="px-3 py-1.5 text-xs">{r.vendor || ''}</td>
                      <td className="px-3 py-1.5 text-right">
                        <div className="inline-flex gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs"
                            onClick={() => api.openExternal(`http://${r.ip}/`)}
                            title="Apri Web UI"
                          >
                            <Globe className="size-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs"
                            onClick={() => api.openExternal(`file:////${r.ip}`)}
                            title="Apri SMB (Esplora risorse)"
                          >
                            <Folder className="size-3" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  )
}

// ipNum — confronto numerico IP per sort stabile.
function ipNum(s: string): number {
  const m = s.split('.').map(Number)
  if (m.length !== 4 || m.some((n) => isNaN(n))) return 0
  return ((m[0] << 24) >>> 0) + ((m[1] << 16) >>> 0) + ((m[2] << 8) >>> 0) + m[3]
}
