// Package proto defines the wire protocol between the 86NocAgent and the
// 86NOC backend. The protocol is JSON over a single persistent WebSocket
// connection, framed as one message per WebSocket frame.
//
// Direction conventions:
//   - "agent -> server" messages have Type values prefixed with "agent."
//   - "server -> agent" messages have Type values prefixed with "server."
//
// Every message carries a monotonically increasing Seq number per direction
// and an optional CorrID used to correlate a server command with its agent
// reply.
package proto

import (
	"encoding/json"
	"time"
)

// Protocol version. Bump on any breaking wire change.
const ProtocolVersion = 1

// Frame is the outer envelope for every WebSocket message.
type Frame struct {
	V       int             `json:"v"`               // protocol version
	Type    string          `json:"type"`            // see Type* constants
	Seq     uint64          `json:"seq"`             // sender-side sequence
	CorrID  string          `json:"corr_id,omitempty"` // request/response correlation
	SentAt  time.Time       `json:"sent_at"`         // sender wall clock (UTC)
	Payload json.RawMessage `json:"payload,omitempty"`
}

// Agent -> Server message types
const (
	TypeAgentHello     = "agent.hello"      // first message after connect
	TypeAgentHeartbeat = "agent.heartbeat"  // periodic liveness + self-telemetry
	TypeAgentEvent     = "agent.event"      // discovery/poll result push
	TypeAgentReply     = "agent.reply"      // reply to a server command
	TypeAgentLog       = "agent.log"        // structured log shipping
)

// Server -> Agent message types
const (
	TypeServerWelcome = "server.welcome" // accept hello + push config
	TypeServerCommand = "server.command" // imperative command (force_scan, ...)
	TypeServerConfig  = "server.config"  // push new configuration
	TypeServerPing    = "server.ping"    // server-side keepalive
)

// AgentHello is sent immediately after the WebSocket handshake completes.
// The backend uses this to authenticate the agent (Token), bind the
// connection to a tenant (ClientID) and persist agent metadata.
type AgentHello struct {
	AgentID      string            `json:"agent_id"`      // stable UUID, generated at install
	ClientID     string            `json:"client_id"`     // tenant the agent belongs to
	Token        string            `json:"token"`         // shared secret / bearer
	Hostname     string            `json:"hostname"`
	OS           string            `json:"os"`            // windows/linux/darwin
	Arch         string            `json:"arch"`          // amd64/arm64
	AgentVersion string            `json:"agent_version"` // semver of the binary
	BootTime     time.Time         `json:"boot_time"`
	IPs          []string          `json:"ips"`
	Capabilities []string          `json:"capabilities"`  // discovery.arp, discovery.mdns, poll.snmp, ...
	Labels       map[string]string `json:"labels,omitempty"`
}

// ServerWelcome confirms the agent is registered and pushes the operational
// configuration (poll intervals, SNMP communities, scan ranges, ...).
type ServerWelcome struct {
	AcceptedAt time.Time       `json:"accepted_at"`
	SessionID  string          `json:"session_id"`
	Config     json.RawMessage `json:"config,omitempty"`
}

// AgentHeartbeat is sent every HeartbeatInterval. It carries lightweight
// self-telemetry so the backend can detect a stuck agent in seconds, not
// in tens of minutes (the historical PowerShell connector failure mode).
type AgentHeartbeat struct {
	Uptime         time.Duration `json:"uptime_ns"`
	Goroutines     int           `json:"goroutines"`
	MemAllocBytes  uint64        `json:"mem_alloc_bytes"`
	CPUPercent     float64       `json:"cpu_percent"`
	ErrorsLast5min uint64        `json:"errors_last_5min"`
	ModulesAlive   []string      `json:"modules_alive"` // discovery.arp, poll.snmp, ...
	ModulesStuck   []string      `json:"modules_stuck"` // any module whose worker missed deadline
	LastScanAt     *time.Time    `json:"last_scan_at,omitempty"`
	LastPollAt     *time.Time    `json:"last_poll_at,omitempty"`
}

// ServerCommand is an imperative instruction sent from the backend.
type ServerCommand struct {
	Name string          `json:"name"` // see Command* constants below
	Args json.RawMessage `json:"args,omitempty"`
}

// Supported command names (server -> agent)
const (
	CmdPing            = "ping"             // returns AgentReply with empty payload
	CmdForceLanScan    = "force_lan_scan"   // run discovery cycle now
	CmdForceSNMPPoll   = "force_snmp_poll"  // poll a single device or whole pool
	CmdGetMetrics      = "get_metrics"      // return live system + agent metrics
	CmdRestartModule   = "restart_module"   // restart a specific worker (args.module)
	CmdRunDiagnostics  = "run_diagnostics"  // collect crash dumps, last logs, port reachability
	CmdSelfUpdate      = "self_update"      // download + apply new binary
	CmdShutdown        = "shutdown"         // graceful exit (watchdog will respawn)
	CmdWebProxy        = "web_proxy"        // proxy HTTP request to an internal device (web console live)
)

// AgentReply is the response to a ServerCommand. CorrID in the Frame
// matches the original ServerCommand frame.
type AgentReply struct {
	OK      bool            `json:"ok"`
	Error   string          `json:"error,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
}

// AgentEvent is an unsolicited push (discovery batch, poll result, ...).
type AgentEvent struct {
	Kind string          `json:"kind"` // see Event* constants below
	Data json.RawMessage `json:"data"`
}

const (
	EventDiscoveryBatch = "discovery_batch" // []DiscoveredEndpoint
	EventSNMPPoll       = "snmp_poll"       // SNMPPollResult
	EventPingPoll       = "ping_poll"       // PingPollResult (ICMP/TCP reachability)
	EventModuleStuck    = "module_stuck"    // module name + last deadline
	EventCrashRecovered = "crash_recovered" // agent recovered after a panic
	EventSysMetrics     = "sys_metrics"     // SysMetricsResult (CPU/RAM/Disk host)
)

// DiscoveredEndpoint is one endpoint observed on the LAN by any discovery
// module (ARP, mDNS, SNMP CAM/LLDP).
type DiscoveredEndpoint struct {
	IP            string            `json:"ip"`
	MAC           string            `json:"mac,omitempty"`
	Hostname      string            `json:"hostname,omitempty"`
	Vendor        string            `json:"vendor,omitempty"`
	Source        string            `json:"source"` // arp / mdns / snmp_cam / lldp / scanner
	FirstSeenAt   time.Time         `json:"first_seen_at"`
	LastSeenAt    time.Time         `json:"last_seen_at"`
	Attributes    map[string]string `json:"attributes,omitempty"`
}

// SNMPPollResult is the outcome of polling a single SNMP target.
type SNMPPollResult struct {
	Target      string            `json:"target"`
	Reachable   bool              `json:"reachable"`
	Latency     time.Duration     `json:"latency_ns"`
	SysName     string            `json:"sys_name,omitempty"`
	SysDescr    string            `json:"sys_descr,omitempty"`
	SysObjectID string            `json:"sys_object_id,omitempty"`
	Uptime      time.Duration     `json:"uptime_ns,omitempty"`
	Error       string            `json:"error,omitempty"`
	OIDs        map[string]string `json:"oids,omitempty"`
}

// PingPollResult is the outcome of probing a single device with ICMP
// echo (and an optional TCP fallback). It is the lightweight liveness
// signal used by the backend to drive UP/DOWN state of every managed
// device, replacing the legacy PowerShell Connector polling loop.
type PingPollResult struct {
	Target    string        `json:"target"`              // IP address
	Reachable bool          `json:"reachable"`           // true if any probe succeeded
	Method    string        `json:"method,omitempty"`    // icmp / tcp
	Latency   time.Duration `json:"latency_ns,omitempty"`// best RTT observed
	LossPct   float64       `json:"loss_pct,omitempty"`  // 0..100 across probes
	Error     string        `json:"error,omitempty"`
}

// SysMetricsResult is the periodic snapshot of the agent host (Windows /
// Linux). Replaces SNMP polling for Windows servers where the agent runs
// directly: CPU/RAM/Disk are sampled via gopsutil (WMI counters on Windows
// natively, /proc on Linux).
type SysMetricsResult struct {
	SampledAt    time.Time            `json:"sampled_at"`
	Hostname     string               `json:"hostname"`
	OS           string               `json:"os"`
	Platform     string               `json:"platform,omitempty"`     // e.g. "Microsoft Windows Server 2019"
	UptimeSec    uint64               `json:"uptime_sec"`
	BootTime     time.Time            `json:"boot_time"`
	CPUPercent   float64              `json:"cpu_percent"`            // averaged across all cores
	CPUCores     int                  `json:"cpu_cores"`
	LoadAvg1     float64              `json:"load_avg_1,omitempty"`   // unix only
	MemTotalMB   uint64               `json:"mem_total_mb"`
	MemUsedMB    uint64               `json:"mem_used_mb"`
	MemUsedPct   float64              `json:"mem_used_pct"`
	SwapUsedMB   uint64               `json:"swap_used_mb,omitempty"`
	SwapUsedPct  float64              `json:"swap_used_pct,omitempty"`
	Disks        []SysMetricsDisk     `json:"disks,omitempty"`
	NetTotalRX   uint64               `json:"net_total_rx_bytes,omitempty"`
	NetTotalTX   uint64               `json:"net_total_tx_bytes,omitempty"`
	ProcCount    int                  `json:"proc_count,omitempty"`
}

// SysMetricsDisk is the per-volume snapshot embedded in SysMetricsResult.
type SysMetricsDisk struct {
	Mount      string  `json:"mount"`        // "C:" / "/" / "/var"
	FSType     string  `json:"fs_type,omitempty"`
	TotalGB    float64 `json:"total_gb"`
	UsedGB     float64 `json:"used_gb"`
	UsedPct    float64 `json:"used_pct"`
}

// AgentLog is a structured log line shipped to the backend.
type AgentLog struct {
	Level  string            `json:"level"`  // debug/info/warn/error
	Module string            `json:"module"`
	Msg    string            `json:"msg"`
	Fields map[string]string `json:"fields,omitempty"`
}
