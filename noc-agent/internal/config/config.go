// Package config loads the agent configuration from a YAML file plus
// environment variable overrides. The file path is resolved in this order:
//
//  1. --config CLI flag
//  2. NOCAGENT_CONFIG environment variable
//  3. /etc/86nocagent/agent.yaml (Linux/macOS)
//  4. C:\ProgramData\86NocAgent\agent.yaml (Windows)
package config

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// Config is the root agent configuration object.
type Config struct {
	AgentID  string `yaml:"agent_id"`  // stable UUID, generated at first run if empty
	ClientID string `yaml:"client_id"` // tenant id assigned by the backend
	Token    string `yaml:"token"`     // bearer token for backend auth

	Backend Backend `yaml:"backend"`

	Heartbeat   time.Duration `yaml:"heartbeat"`     // default 15s
	ReconnectMin time.Duration `yaml:"reconnect_min"` // default 1s
	ReconnectMax time.Duration `yaml:"reconnect_max"` // default 60s

	Discovery DiscoveryConfig `yaml:"discovery"`
	SNMP      SNMPConfig      `yaml:"snmp"`
	Ping      PingConfig      `yaml:"ping"`
	SysMetrics SysMetricsConfig `yaml:"sysmetrics"`
	Watchdog  WatchdogConfig  `yaml:"watchdog"`
	Update    UpdateConfig    `yaml:"update"`

	Labels map[string]string `yaml:"labels,omitempty"`
}

type Backend struct {
	URL          string `yaml:"url"`           // wss://argus.86bit.it/api/agent/ws
	InsecureSkip bool   `yaml:"insecure_skip"` // skip TLS verify (dev only)
}

type DiscoveryConfig struct {
	Enabled  bool          `yaml:"enabled"`
	Interval time.Duration `yaml:"interval"` // full LAN sweep cadence, default 5m
	ARP      bool          `yaml:"arp"`
	MDNS     bool          `yaml:"mdns"`
	Subnets  []string      `yaml:"subnets,omitempty"` // CIDRs to actively probe; empty = local only
}

type SNMPConfig struct {
	Enabled     bool          `yaml:"enabled"`
	Interval    time.Duration `yaml:"interval"`     // default 60s
	Communities []string      `yaml:"communities"`  // tried in order
	Timeout     time.Duration `yaml:"timeout"`      // default 2s
	Retries     int           `yaml:"retries"`      // default 1
	Targets     []SNMPTarget  `yaml:"targets,omitempty"`
}

type SNMPTarget struct {
	IP          string `yaml:"ip"`
	Name        string `yaml:"name,omitempty"`
	Community   string `yaml:"community,omitempty"`
	Profile     string `yaml:"profile,omitempty"`      // generic / zyxel / mikrotik / printer ...
	SNMPVersion string `yaml:"snmp_version,omitempty"` // v1 / v2c / v3
	SNMPPort    int    `yaml:"snmp_port,omitempty"`    // default 161
}

// PingConfig drives the ICMP live-polling loop. The agent invokes the
// native `ping` binary of the host OS once per Interval against every
// Target and reports UP/DOWN + RTT to the backend via an EventPingPoll
// frame. The backend applies a 3-consecutive-failure threshold before
// flipping managed_devices.status to "offline" (avoids flapping).
type PingConfig struct {
	Enabled  bool          `yaml:"enabled"`
	Interval time.Duration `yaml:"interval"` // default 60s
	Timeout  time.Duration `yaml:"timeout"`  // default 2s per probe
	Count    int           `yaml:"count"`    // probes per cycle, default 1
	Targets  []PingTarget  `yaml:"targets,omitempty"`
}

type PingTarget struct {
	IP   string `yaml:"ip"`
	Name string `yaml:"name,omitempty"`
}

// SysMetricsConfig drives the local-host monitoring loop. When the agent
// runs ON the box you want to monitor (typical for Windows servers), use
// this instead of SNMP — gopsutil reads WMI counters natively on Windows
// and /proc on Linux. Enabled è ON di default (low-cost: 1 sample/min).
type SysMetricsConfig struct {
	Enabled  bool          `yaml:"enabled"`
	Interval time.Duration `yaml:"interval"` // default 60s
}

type WatchdogConfig struct {
	Enabled         bool          `yaml:"enabled"`
	HeartbeatFile   string        `yaml:"heartbeat_file"`   // touched by agent every tick
	StaleAfter      time.Duration `yaml:"stale_after"`      // default 90s
	RestartCmd      []string      `yaml:"restart_cmd,omitempty"`
}

type UpdateConfig struct {
	Enabled       bool          `yaml:"enabled"`
	ManifestURL   string        `yaml:"manifest_url"`   // GET signed manifest
	CheckInterval time.Duration `yaml:"check_interval"` // default 1h
	PublicKey     string        `yaml:"public_key"`     // Ed25519 hex; empty = unsigned not allowed
}

// Default returns a Config populated with safe defaults.
func Default() Config {
	return Config{
		Heartbeat:    15 * time.Second,
		ReconnectMin: 1 * time.Second,
		ReconnectMax: 60 * time.Second,
		Discovery: DiscoveryConfig{
			Enabled:  true,
			Interval: 5 * time.Minute,
			ARP:      true,
			MDNS:     true,
		},
		SNMP: SNMPConfig{
			Enabled:     true,
			Interval:    60 * time.Second,
			Communities: []string{"public"},
			Timeout:     2 * time.Second,
			Retries:     1,
		},
		Ping: PingConfig{
			Enabled:  true,
			Interval: 60 * time.Second,
			Timeout:  2 * time.Second,
			Count:    1,
		},
		SysMetrics: SysMetricsConfig{
			Enabled:  true,
			Interval: 60 * time.Second,
		},
		Watchdog: WatchdogConfig{
			Enabled:       true,
			HeartbeatFile: defaultHeartbeatFile(),
			StaleAfter:    90 * time.Second,
		},
		Update: UpdateConfig{
			Enabled:       true,
			CheckInterval: 1 * time.Hour,
		},
	}
}

// Load reads a YAML config from disk and merges it on top of Default().
// Environment variables take precedence over file values.
func Load(path string) (Config, error) {
	cfg := Default()

	if path == "" {
		path = resolvePath()
	}

	if path != "" {
		raw, err := os.ReadFile(path)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return cfg, fmt.Errorf("read config %s: %w", path, err)
		}
		if err == nil {
			if err := yaml.Unmarshal(raw, &cfg); err != nil {
				return cfg, fmt.Errorf("parse config %s: %w", path, err)
			}
		}
	}

	applyEnv(&cfg)

	// Persist a stable agent_id across restarts. Senza questo l'agent
	// genera un UUID nuovo ogni reboot/restart del servizio, e il backend
	// finisce con N ghost record in managed_agents per lo stesso cliente.
	// Si era arrivati a 14 ghost per il cliente 86BITOffice prima del fix.
	if cfg.AgentID == "" {
		cfg.AgentID = getOrCreateStableAgentID()
	}

	if cfg.Backend.URL == "" {
		return cfg, errors.New("backend.url is required (set in YAML or NOCAGENT_BACKEND_URL)")
	}
	if cfg.ClientID == "" {
		return cfg, errors.New("client_id is required (set in YAML or NOCAGENT_CLIENT_ID)")
	}
	if cfg.Token == "" {
		return cfg, errors.New("token is required (set in YAML or NOCAGENT_TOKEN)")
	}

	return cfg, nil
}

func applyEnv(cfg *Config) {
	if v := os.Getenv("NOCAGENT_BACKEND_URL"); v != "" {
		cfg.Backend.URL = v
	}
	if v := os.Getenv("NOCAGENT_CLIENT_ID"); v != "" {
		cfg.ClientID = v
	}
	if v := os.Getenv("NOCAGENT_TOKEN"); v != "" {
		cfg.Token = v
	}
	if v := os.Getenv("NOCAGENT_AGENT_ID"); v != "" {
		cfg.AgentID = v
	}
	if v := os.Getenv("NOCAGENT_INSECURE_SKIP"); v == "1" || v == "true" {
		cfg.Backend.InsecureSkip = true
	}
}

func resolvePath() string {
	if v := os.Getenv("NOCAGENT_CONFIG"); v != "" {
		return v
	}
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent.yaml")
	}
	return "/etc/86nocagent/agent.yaml"
}

func defaultHeartbeatFile() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "heartbeat.tick")
	}
	return "/var/lib/86nocagent/heartbeat.tick"
}

// defaultAgentIDFile is the well-known location used to persist the stable
// agent UUID across restarts. Kept separate from agent.yaml so the
// installer/PowerShell wrapper can freely rewrite the yaml without losing
// the identity (the yaml is regenerated at every install/update).
func defaultAgentIDFile() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "86NocAgent", "agent_id.txt")
	}
	return "/var/lib/86nocagent/agent_id"
}

// getOrCreateStableAgentID returns a UUID that survives restarts.
//
// Lookup order:
//  1. existing content of defaultAgentIDFile (a hex UUID without dashes)
//  2. generate a brand new UUID via transport.NewAgentID() and persist it
//
// On failure to write the file the function still returns a valid (ephemeral)
// UUID — the agent must never refuse to start because of a missing identity
// file. The next successful write will make the ID stable from then on.
//
// Importing transport here would create a cycle (transport imports config),
// so we inline the generation: 16 random bytes, hex-encoded.
func getOrCreateStableAgentID() string {
	path := defaultAgentIDFile()
	if b, err := os.ReadFile(path); err == nil {
		id := strings.TrimSpace(string(b))
		if isValidAgentID(id) {
			return id
		}
	}
	id := newRandomAgentID()
	_ = os.MkdirAll(filepath.Dir(path), 0o755)
	_ = os.WriteFile(path, []byte(id), 0o644)
	return id
}

// isValidAgentID accepts 32-char hex strings (UUID without dashes), which is
// the canonical format used by transport.NewAgentID().
func isValidAgentID(s string) bool {
	if len(s) != 32 {
		return false
	}
	for _, c := range s {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return false
		}
	}
	return true
}

func newRandomAgentID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		// crypto/rand failure is so rare we fall back to a timestamp-derived
		// id rather than panicking; still 16 bytes so the format is preserved.
		ts := time.Now().UnixNano()
		for i := 0; i < 16; i++ {
			b[i] = byte(ts >> (i * 8))
		}
	}
	return hex.EncodeToString(b)
}
