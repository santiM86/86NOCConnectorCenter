import { useState } from 'react'
import { Copy, ExternalLink, FolderOpen, Play, RotateCcw, Square } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { api, type AgentInfo } from '@/lib/bridge'

interface Props {
  agent: AgentInfo | null
}

export function SettingsPage({ agent }: Props) {
  const [copied, setCopied] = useState<string | null>(null)
  const copy = async (label: string, val: string) => {
    try {
      await navigator.clipboard.writeText(val)
      setCopied(label)
      setTimeout(() => setCopied(null), 1500)
    } catch {}
  }

  return (
    <div className="p-6 space-y-5">
      <header>
        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Configurazione</div>
        <h1 className="text-2xl font-bold tracking-tight">Impostazioni</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Identità agent, controllo servizio, accesso al file di configurazione.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Identità Agent</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <FieldRow label="Agent ID" value={agent?.agent_id} onCopy={(v) => copy('agent_id', v)} copied={copied === 'agent_id'} />
          <FieldRow label="Client ID" value={agent?.client_id} onCopy={(v) => copy('client_id', v)} copied={copied === 'client_id'} />
          <FieldRow label="Token" value={agent?.token} mask onCopy={(v) => copy('token', v)} copied={copied === 'token'} />
          <FieldRow label="Backend URL" value={agent?.backend_url} onCopy={(v) => copy('url', v)} copied={copied === 'url'} />
          <FieldRow label="Hostname locale" value={agent?.hostname} readonly />
          <FieldRow label="Ruolo" value={agent?.role} readonly />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Controllo Servizio</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between p-3 rounded-md bg-secondary/40">
            <div className="flex items-center gap-3">
              <ServiceDot state={agent?.service_state} />
              <div>
                <div className="text-sm font-medium">86NocAgent</div>
                <div className="text-xs text-muted-foreground">Servizio principale</div>
              </div>
            </div>
            <Badge variant={agent?.service_state === 'running' ? 'success' : 'destructive'}>
              {agent?.service_state ?? 'unknown'}
            </Badge>
          </div>
          <div className="flex items-center justify-between p-3 rounded-md bg-secondary/40">
            <div className="flex items-center gap-3">
              <ServiceDot state={agent?.watchdog_state} />
              <div>
                <div className="text-sm font-medium">86NocWatchdog</div>
                <div className="text-xs text-muted-foreground">Restart automatico in caso di crash</div>
              </div>
            </div>
            <Badge variant={agent?.watchdog_state === 'running' ? 'success' : 'destructive'}>
              {agent?.watchdog_state ?? 'unknown'}
            </Badge>
          </div>
          <div className="flex gap-2 pt-2 flex-wrap">
            <Button data-testid="svc-start" variant="outline" size="sm" onClick={() => api.startService()}>
              <Play />
              Start
            </Button>
            <Button data-testid="svc-stop" variant="outline" size="sm" onClick={() => api.stopService()}>
              <Square />
              Stop
            </Button>
            <Button data-testid="svc-restart" size="sm" onClick={() => api.restartService()}>
              <RotateCcw />
              Restart
            </Button>
            <div className="flex-1" />
            <Button data-testid="open-yaml" variant="ghost" size="sm" onClick={() => api.openConfig()}>
              <FolderOpen />
              Apri cartella config
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Versioni</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Argus Desktop (questa app)</span>
            <span className="font-mono">5.0.0</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Agent service (`nocagent.exe`)</span>
            <span className="font-mono">{agent?.agent_version || '—'}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Config file</span>
            <span className="font-mono text-xs text-muted-foreground truncate ml-3" title={agent?.config_path}>
              {agent?.config_path || '—'}
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function FieldRow({
  label, value, mask, readonly, onCopy, copied,
}: {
  label: string; value?: string; mask?: boolean; readonly?: boolean
  onCopy?: (v: string) => void; copied?: boolean
}) {
  const display = mask && value ? value.slice(0, 6) + '••••••••••' + value.slice(-4) : value || '—'
  return (
    <div className="grid grid-cols-1 md:grid-cols-[160px_1fr_auto] gap-2 md:items-center">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <Input
        data-testid={`field-${label.toLowerCase().replace(' ', '-')}`}
        readOnly
        value={display}
        className="font-mono text-xs"
      />
      {!readonly && onCopy && value && (
        <Button variant="ghost" size="sm" onClick={() => onCopy(value)}>
          <Copy />
          {copied ? 'Copiato!' : 'Copia'}
        </Button>
      )}
    </div>
  )
}

function ServiceDot({ state }: { state?: string }) {
  const color =
    state === 'running' ? 'bg-success shadow-success/50' :
    state === 'starting' || state === 'stopping' ? 'bg-warning shadow-warning/50' :
    'bg-destructive shadow-destructive/50'
  return <span className={`size-2.5 rounded-full shadow-[0_0_8px] ${color}`} />
}
