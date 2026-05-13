import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, Filter, Pause, Play, RefreshCcw, Search } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { api, type LogLine } from '@/lib/bridge'
import { cn } from '@/lib/utils'

const LEVEL_FILTERS: Array<{ key: string; label: string; tone: string }> = [
  { key: 'all', label: 'TUTTI', tone: 'border-border text-muted-foreground' },
  { key: 'info', label: 'INFO', tone: 'border-info/30 text-info' },
  { key: 'warn', label: 'WARN', tone: 'border-warning/30 text-warning' },
  { key: 'error', label: 'ERROR', tone: 'border-destructive/30 text-destructive' },
]

export function LogsPage() {
  const [lines, setLines] = useState<LogLine[]>([])
  const [query, setQuery] = useState('')
  const [level, setLevel] = useState('all')
  const [follow, setFollow] = useState(true)
  const scrollerRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    const data = await api.readLogs(500)
    setLines(data ?? [])
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (follow && scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight
    }
  }, [lines, follow])

  const filtered = useMemo(() => {
    return lines.filter((l) => {
      if (level !== 'all' && (l.level || 'info').toLowerCase() !== level) return false
      if (!query) return true
      const q = query.toLowerCase()
      return (
        (l.message || '').toLowerCase().includes(q) ||
        (l.module || '').toLowerCase().includes(q)
      )
    })
  }, [lines, query, level])

  const exportLogs = () => {
    const blob = new Blob([filtered.map((l) => JSON.stringify(l)).join('\n')], { type: 'application/x-ndjson' })
    const u = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = u
    a.download = `argus-log-${new Date().toISOString().slice(0, 19)}.ndjson`
    a.click()
    URL.revokeObjectURL(u)
  }

  return (
    <div className="p-6 space-y-4 h-full flex flex-col">
      <header className="flex items-end justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Diagnostica</div>
          <h1 className="text-2xl font-bold tracking-tight">Log live</h1>
        </div>
        <div className="flex gap-2">
          <Button data-testid="logs-pause" variant="outline" size="sm" onClick={() => setFollow((v) => !v)}>
            {follow ? <Pause /> : <Play />}
            {follow ? 'Pausa scroll' : 'Riprendi'}
          </Button>
          <Button data-testid="logs-refresh" variant="outline" size="sm" onClick={load}>
            <RefreshCcw />
            Refresh
          </Button>
          <Button data-testid="logs-export" variant="outline" size="sm" onClick={exportLogs}>
            <Download />
            Export
          </Button>
        </div>
      </header>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative max-w-sm flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            data-testid="logs-search"
            placeholder="Cerca nel testo / nel modulo…"
            className="pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground"><Filter className="size-3.5" /></div>
        {LEVEL_FILTERS.map((f) => (
          <button
            key={f.key}
            data-testid={`logs-level-${f.key}`}
            onClick={() => setLevel(f.key)}
            className={cn(
              'px-2.5 py-1.5 rounded-md border bg-card text-[10px] font-bold tracking-wider transition-colors',
              level === f.key ? f.tone : 'border-border text-muted-foreground/60 hover:text-muted-foreground'
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <Card className="flex-1 overflow-hidden p-0 font-mono text-xs">
        <div ref={scrollerRef} className="h-full overflow-auto">
          <table className="w-full">
            <tbody>
              {filtered.map((l, i) => (
                <tr key={i} className="border-b border-border/40 hover:bg-accent/5">
                  <td className="px-3 py-1.5 whitespace-nowrap text-muted-foreground text-[10px] align-top">
                    {(l.timestamp || '').replace('T', ' ').split('.')[0]}
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <LevelTag level={l.level} />
                  </td>
                  <td className="px-2 py-1.5 align-top text-muted-foreground">{l.module || '—'}</td>
                  <td className="px-3 py-1.5 align-top break-all">{l.message}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={4} className="p-10 text-center text-muted-foreground">Nessun log corrispondente.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function LevelTag({ level }: { level?: string }) {
  const lvl = (level || 'info').toLowerCase()
  const cls =
    lvl === 'error' ? 'bg-destructive/15 text-destructive' :
    lvl === 'warn' ? 'bg-warning/15 text-warning' :
    lvl === 'debug' ? 'bg-muted text-muted-foreground' :
    'bg-info/15 text-info'
  return (
    <span className={cn('inline-block px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wider', cls)}>
      {lvl.toUpperCase()}
    </span>
  )
}
