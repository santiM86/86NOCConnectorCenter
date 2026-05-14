/**
 * Bridge unico con il backend Go (Wails bindings).
 *
 * Il frontend non chiama mai direttamente window.go.main.App.X — passa
 * tutto da qui così:
 *   1. Mock automatico se Wails non è disponibile (dev nel browser).
 *   2. Tipizzazione centralizzata: i tipi seguono `app.go::AgentInfo` ecc.
 *   3. Logging uniforme delle chiamate (utile in diagnostica).
 */

export interface AgentInfo {
  agent_id: string
  client_id: string
  token: string
  backend_url: string
  hostname: string
  role: 'master' | 'scanner' | string
  agent_version: string
  service_state: 'running' | 'stopped' | 'starting' | 'stopping' | 'unknown'
  watchdog_state: 'running' | 'stopped' | 'starting' | 'stopping' | 'unknown'
  config_path: string
}

export interface HealthSnapshot {
  connected: boolean
  client_id: string
  agent_id: string
  agents_online: number
  rtt_ms: number
  hostname?: string
  agent_version?: string
  last_heartbeat_at?: string
  connected_at?: string
  error?: string
}

export interface Device {
  ip: string
  name?: string
  status: 'online' | 'offline' | 'pending' | string
  last_poll_at?: string
  latency_ms?: number
  device_type?: string
}

export interface DiscoveredEndpoint {
  ip: string
  mac?: string
  hostname?: string
  vendor?: string
  source: string
  last_seen_at?: string
  first_seen_at?: string
}

export interface LogLine {
  timestamp: string
  level: string
  module?: string
  message: string
}

// ----- private helpers -------------------------------------------------

const hasWails = (): boolean =>
  typeof window !== 'undefined' && !!window.go?.main?.App

async function call<T>(method: string, ...args: unknown[]): Promise<T> {
  if (!hasWails()) {
    // Mock dev: ritorna dati finti coerenti coi tipi.
    return mock<T>(method)
  }
  const fn = window.go!.main!.App![method]
  if (!fn) throw new Error(`Wails binding mancante: ${method}`)
  try {
    return (await fn(...args)) as T
  } catch (e) {
    console.error(`[bridge] ${method} failed`, e)
    throw e
  }
}

// Mock per dev browser (no Wails). Sostituito a runtime quando girando
// dentro WebView2.
function mock<T>(method: string): T {
  const sample: Record<string, unknown> = {
    AppVersion: '5.0.0-dev',
    AgentSnapshot: {
      agent_id: 'dev-mock-agent',
      client_id: '57cb2e2b-938c-4f6d-a1a3-df5368de00e9',
      token: 'noc_dev_mock_token',
      backend_url: 'https://argus.86bit.it',
      hostname: 'DEV-LAB',
      role: 'master',
      agent_version: '4.2.0-dev',
      service_state: 'running',
      watchdog_state: 'running',
      config_path: 'C:\\ProgramData\\86NocAgent\\agent.yaml',
    } as AgentInfo,
    RefreshAgent: undefined as never,
    HealthCheck: {
      connected: true,
      client_id: '57cb2e2b-938c-4f6d-a1a3-df5368de00e9',
      agent_id: 'dev-mock-agent',
      agents_online: 1,
      rtt_ms: 8.4,
      hostname: 'DEV-LAB',
      agent_version: '4.2.0-dev',
      last_heartbeat_at: new Date().toISOString(),
      connected_at: new Date(Date.now() - 3600 * 1000).toISOString(),
    } as HealthSnapshot,
    ListDevices: [
      { ip: '192.168.1.1', name: 'core-switch', status: 'online', latency_ms: 1.2, device_type: 'switch' },
      { ip: '192.168.1.10', name: 'printer-hp', status: 'online', latency_ms: 4.6, device_type: 'printer' },
      { ip: '192.168.1.50', name: 'firewall', status: 'offline', latency_ms: 0, device_type: 'firewall' },
      { ip: '192.168.1.99', name: 'windows-pc', status: 'pending', device_type: 'workstation' },
    ] as Device[],
    ListDiscovered: [
      { ip: '192.168.1.105', mac: 'aa:bb:cc:11:22:33', hostname: 'pc-fabio', vendor: 'Intel Corporate', source: 'arp', last_seen_at: new Date().toISOString() },
      { ip: '192.168.1.110', mac: '00:1a:2b:3c:4d:5e', hostname: '', vendor: 'Apple, Inc.', source: 'mdns', last_seen_at: new Date().toISOString() },
    ] as DiscoveredEndpoint[],
    ReadLogs: Array.from({ length: 20 }, (_, i) => ({
      timestamp: new Date(Date.now() - i * 4000).toISOString(),
      level: i % 7 === 0 ? 'warn' : 'info',
      module: ['transport', 'discovery', 'ping', 'snmp'][i % 4],
      message: i % 7 === 0 ? 'connection retry attempt 2' : `heartbeat ok, latency 8.${i}ms`,
    })) as LogLine[],
  }
  return sample[method] as T
}

// ----- public API ------------------------------------------------------

export const api = {
  appVersion: () => call<string>('AppVersion'),
  agentSnapshot: () => call<AgentInfo>('AgentSnapshot'),
  refreshAgent: () => call<AgentInfo>('RefreshAgent'),
  healthCheck: () => call<HealthSnapshot>('HealthCheck'),
  listDevices: () => call<Device[]>('ListDevices'),
  listDiscovered: () => call<DiscoveredEndpoint[]>('ListDiscovered'),
  testPing: (ip: string) => call<Record<string, unknown>>('TestPing', ip),
  startService: () => call<void>('StartService'),
  stopService: () => call<void>('StopService'),
  restartService: () => call<void>('RestartService'),
  readLogs: (n = 200) => call<LogLine[]>('ReadLogs', n),
  openDashboard: () => call<void>('OpenDashboard'),
  openExternal: (url: string) => call<void>('OpenExternal', url),
  openConfig: () => call<void>('OpenConfig'),
}

export const isWails = hasWails
