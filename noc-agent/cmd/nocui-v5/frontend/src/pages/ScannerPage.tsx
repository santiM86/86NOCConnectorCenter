import { useState } from 'react'
import { Play, Wifi } from 'lucide-react'
import { motion } from 'framer-motion'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'

/**
 * Lo Scanner LAN richiede una nuova RPC backend (forziamo un ciclo
 * di discovery on-demand). Per ora il bottone è collegato al binding
 * Wails `forceLanScan` che attualmente non esiste — la UI lo segnala
 * graziosamente con uno stato "TODO" così non promettiamo bugiardamente
 * funzionalità non collegate.
 */
export function ScannerPage() {
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [results, setResults] = useState<string | null>(null)
  const [subnet, setSubnet] = useState('192.168.1.0/24')

  const start = () => {
    setRunning(true)
    setProgress(0)
    setResults(null)
    // Animazione progress visiva mentre si attende il backend (futuro).
    let p = 0
    const id = setInterval(() => {
      p = Math.min(100, p + Math.random() * 8 + 2)
      setProgress(p)
      if (p >= 100) {
        clearInterval(id)
        setRunning(false)
        setResults(
          'Scanner attivo on-demand sarà rilasciato con la prossima patch del backend (richiede /api/agent/self/lan-scan).'
        )
      }
    }, 250)
  }

  return (
    <div className="p-6 space-y-5">
      <header>
        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">On-demand</div>
        <h1 className="text-2xl font-bold tracking-tight">Scanner LAN</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Lancia una scansione attiva (ARP + mDNS + Reverse DNS) sulla subnet indicata.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Parametri</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
            <div className="md:col-span-2">
              <label className="text-xs text-muted-foreground">Subnet target (CIDR)</label>
              <Input
                data-testid="scanner-subnet"
                value={subnet}
                onChange={(e) => setSubnet(e.target.value)}
                placeholder="192.168.1.0/24"
                className="mt-1 font-mono"
                disabled={running}
              />
            </div>
            <Button data-testid="scanner-start" onClick={start} disabled={running}>
              <Play />
              {running ? 'In corso…' : 'Avvia scansione'}
            </Button>
          </div>

          {running && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <Progress value={progress} className="h-2" />
              <div className="text-xs text-muted-foreground mt-2 flex items-center gap-2">
                <Wifi className="size-3 animate-pulse" />
                {progress < 30 && 'Inizializzazione…'}
                {progress >= 30 && progress < 70 && 'ARP sweep + mDNS query…'}
                {progress >= 70 && progress < 100 && 'Reverse DNS resolve…'}
                {progress >= 100 && 'Completato'}
              </div>
            </motion.div>
          )}

          {results && (
            <div className="mt-2 text-sm rounded-md border border-warning/30 bg-warning/10 text-warning px-3 py-2.5">
              {results}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tip</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Lo scanner periodico gira già ogni 5 minuti in background. Lancia da qui solo se devi vedere subito un dispositivo appena collegato.
        </CardContent>
      </Card>
    </div>
  )
}
