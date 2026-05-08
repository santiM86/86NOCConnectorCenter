// Package config loads the agent configuration from a YAML file plus
// environment variable overrides. The file path is resolved in this order:
//
//  1. --config CLI flag
//  2. NOCAGENT_CONFIG environment variable
//  3. /etc/86nocagent/agent.yaml (Linux/macOS)
//  4. C:\ProgramData\86NocAgent\agent.yaml (Windows)
package config

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
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
	IP        string `yaml:"ip"`
	Community string `yaml:"community,omitempty"`
	Profile   string `yaml:"profile,omitempty"` // generic / zyxel / mikrotik / printer ...
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
