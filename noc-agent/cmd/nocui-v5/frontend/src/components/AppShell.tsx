import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity,
  Boxes,
  Compass,
  Cpu,
  ExternalLink,
  FileText,
  Globe,
  Minus,
  Moon,
  Settings as SettingsIcon,
  Square,
  Sun,
  Wifi,
  WifiOff,
  X,
  Zap,
} from 'lucide-react'
import { cn, timeAgo } from '@/lib/utils'
import { useTheme } from '@/lib/theme'
import { api, type AgentInfo, type HealthSnapshot } from '@/lib/bridge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Badge } from '@/components/ui/badge'

type NavKey = 'dashboard' | 'devices' | 'discovery' | 'scanner' | 'logs' | 'settings'

interface NavItem {
  key: NavKey
  label: string
  icon: React.ComponentType<{ className?: string }>
  hint?: string
}

const NAV: NavItem[] = [
  { key: 'dashboard', label: 'Dashboard', icon: Activity, hint: 'Stato real-time agent' },
  { key: 'devices', label: 'Dispositivi', icon: Boxes, hint: 'Live polling ICMP/SNMP' },
  { key: 'discovery', label: 'Auto-Discovery', icon: Compass, hint: 'Endpoint scoperti su LAN' },
  { key: 'scanner', label: 'Scanner LAN', icon: Zap, hint: 'Scansione attiva on-demand' },
  { key: 'logs', label: 'Diagnostica', icon: FileText, hint: 'Log live, ping/SNMP test' },
  { key: 'settings', label: 'Impostazioni', icon: SettingsIcon, hint: 'Token, intervalli, servizio' },
]

interface ShellProps {
  active: NavKey
  onNavigate: (k: NavKey) => void
  children: React.ReactNode
  agent: AgentInfo | null
  health: HealthSnapshot | null
}

export function AppShell({ active, onNavigate, children, agent, health }: ShellProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-full overflow-hidden bg-background text-foreground">
        <Sidebar active={active} onNavigate={onNavigate} />
        <div className="flex flex-1 flex-col min-w-0">
          <TopBar agent={agent} health={health} />
          <main className="flex-1 overflow-auto">
            <AnimatePresence mode="wait">
              <motion.div
                key={active}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                className="h-full"
              >
                {children}
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}

// =============================================================================
// SIDEBAR
// =============================================================================

function Sidebar({ active, onNavigate }: { active: NavKey; onNavigate: (k: NavKey) => void }) {
  return (
    <aside className="w-[210px] shrink-0 border-r border-border bg-card/40 backdrop-blur flex flex-col">
      <div className="px-5 py-5 border-b border-border/60">
        <div className="flex items-center gap-2.5">
          <div className="size-8 rounded-lg bg-primary flex items-center justify-center shadow-lg shadow-primary/30">
            <Cpu className="size-4 text-primary-foreground" strokeWidth={2.4} />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight tracking-tight">ARGUS</div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Desktop</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-2 py-3 space-y-0.5">
        {NAV.map((it) => {
          const Icon = it.icon
          const isActive = it.key === active
          return (
            <button
              key={it.key}
              data-testid={`nav-${it.key}`}
              onClick={() => onNavigate(it.key)}
              className={cn(
                'w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-all relative',
                'hover:bg-accent/10 hover:text-foreground',
                isActive ? 'text-foreground' : 'text-muted-foreground'
              )}
            >
              {isActive && (
                <motion.span
                  layoutId="nav-active-pill"
                  className="absolute inset-0 rounded-md bg-accent/10 border border-accent/20"
                  transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                />
              )}
              <Icon className={cn('size-4 relative z-10 shrink-0', isActive && 'text-primary')} />
              <span className="relative z-10">{it.label}</span>
            </button>
          )
        })}
      </nav>

      <div className="px-3 py-3 border-t border-border/60">
        <ThemeToggle />
      </div>
    </aside>
  )
}

function ThemeToggle() {
  const { theme, setTheme, resolved } = useTheme()
  const cycle = () => setTheme(theme === 'dark' ? 'light' : theme === 'light' ? 'system' : 'dark')
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          data-testid="theme-toggle"
          onClick={cycle}
          className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent/10 transition-colors"
        >
          <span className="capitalize">{theme}</span>
          {resolved === 'dark' ? <Moon className="size-3.5" /> : <Sun className="size-3.5" />}
        </button>
      </TooltipTrigger>
      <TooltipContent side="right">Cambia tema (Dark → Light → System)</TooltipContent>
    </Tooltip>
  )
}

// =============================================================================
// TOP BAR (drag region + status pills + window controls)
// =============================================================================

function TopBar({ agent, health }: { agent: AgentInfo | null; health: HealthSnapshot | null }) {
  const connected = !!health?.connected
  const serviceRunning = agent?.service_state === 'running'

  return (
    <div className="drag-region h-12 flex items-center justify-between px-4 border-b border-border/60 bg-card/30">
      <div className="flex items-center gap-3 no-drag">
        <StatusPill
          label={connected ? 'CENTER ONLINE' : 'CENTER OFFLINE'}
          state={connected ? 'ok' : 'err'}
          tooltip={
            connected
              ? `RTT ${health?.rtt_ms?.toFixed(1)}ms • ${health?.agents_online ?? 0} agent collegati`
              : (health?.error || 'WebSocket non connesso al NOC Center')
          }
          icon={connected ? Wifi : WifiOff}
        />
        <StatusPill
          label={`AGENT ${serviceRunning ? 'RUN' : (agent?.service_state ?? 'UNK').toUpperCase()}`}
          state={serviceRunning ? 'ok' : 'warn'}
          tooltip={`Servizio 86NocAgent: ${agent?.service_state ?? '—'}`}
          icon={Cpu}
        />
        {agent?.hostname && <span className="text-xs text-muted-foreground hidden md:inline">{agent.hostname}</span>}
      </div>

      <div className="flex items-center gap-2 no-drag">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              data-testid="open-dashboard"
              onClick={() => api.openDashboard()}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent/10 transition-colors"
            >
              <Globe className="size-3.5" />
              Dashboard Web
              <ExternalLink className="size-3" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Apri argus.86bit.it nel browser</TooltipContent>
        </Tooltip>

        <WindowControls />
      </div>
    </div>
  )
}

interface PillProps {
  label: string
  state: 'ok' | 'warn' | 'err'
  tooltip?: string
  icon?: React.ComponentType<{ className?: string }>
}
function StatusPill({ label, state, tooltip, icon: Icon }: PillProps) {
  const dotColor =
    state === 'ok' ? 'bg-success shadow-success/50' : state === 'warn' ? 'bg-warning shadow-warning/50' : 'bg-destructive shadow-destructive/50'
  const pill = (
    <div className={cn(
      'flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[11px] font-semibold tracking-wider',
      'border border-border/60 bg-card/60'
    )}>
      <span className={cn('relative inline-flex size-2 rounded-full shadow-[0_0_8px]', dotColor)}>
        {state === 'ok' && <span className={cn('absolute inset-0 rounded-full animate-pulse-dot', dotColor)} />}
      </span>
      {Icon && <Icon className="size-3 text-muted-foreground" />}
      <span className="text-muted-foreground">{label}</span>
    </div>
  )
  if (!tooltip) return pill
  return (
    <Tooltip>
      <TooltipTrigger asChild>{pill}</TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  )
}

function WindowControls() {
  const min = () => window.runtime?.WindowMinimise()
  const tog = () => window.runtime?.WindowToggleMaximise()
  const close = () => window.runtime?.WindowHide()
  return (
    <div className="flex items-center ml-2">
      <button data-testid="win-min" onClick={min} className="size-8 rounded-md flex items-center justify-center hover:bg-accent/10 text-muted-foreground hover:text-foreground transition-colors">
        <Minus className="size-3.5" />
      </button>
      <button data-testid="win-max" onClick={tog} className="size-8 rounded-md flex items-center justify-center hover:bg-accent/10 text-muted-foreground hover:text-foreground transition-colors">
        <Square className="size-3" />
      </button>
      <button data-testid="win-close" onClick={close} className="size-8 rounded-md flex items-center justify-center hover:bg-destructive hover:text-destructive-foreground text-muted-foreground transition-colors">
        <X className="size-3.5" />
      </button>
    </div>
  )
}

// re-export tipi se servono altrove
export type { ShellProps }
